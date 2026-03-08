class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/a9/63/20d5c922f3467f73ba1205c27bc7fa91bfe7f4067b59cf6ec1732dd0f459/agentops_mcp_server-0.4.9.tar.gz"
  sha256 "3e8e8cd90c9f57b9f1a2c00e3f20410defec850cc49d6f152f8a756a5e38e835"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
