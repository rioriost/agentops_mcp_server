class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/16/0c/8c0d1c66fb4fd63476766c7a5e46ee9e5fe619e104a16544099eb48f175d/agentops_mcp_server-0.0.2.tar.gz"
  sha256 "5f0262b3bedcc8ca3a6ddfdfeb4cc8a100fbe6865168d87c0c30e3a1c984082d"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
