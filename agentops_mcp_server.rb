class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/54/1a/8f726ef402be0952248b0b0155e028974e701cbacd0b2ebc4b52a8467ba6/agentops_mcp_server-0.5.0.tar.gz"
  sha256 "4225ce9b0c9e70c0d0a1397af52f9bf1fccb9b6aa736a2640f3ea9af13b441ca"
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
